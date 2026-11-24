#!/usr/bin/env bash
# Despliegue en un AWS Learner Lab: una EC2 con la app Streamlit.
#
#   ./aws-desplegar.sh              simula: muestra lo que haria
#   ./aws-desplegar.sh --aplicar    crea o reutiliza todo y espera a que responda
#   ./aws-desplegar.sh --publico    abre el puerto a todos (por defecto: solo tu IP)
#   ./aws-desplegar.sh --estado     IP, estado y si responde
#   ./aws-desplegar.sh --reanudar   prende la EC2 y reabre el puerto a tu IP actual
#   ./aws-desplegar.sh --detener    apaga la EC2 (no cobra computo)
#
# Credenciales del lab en ~/.aws/credentials. Los secretos se copian de .env al
# Parameter Store como SecureString; no pasan por el user-data ni por el repo.
set -euo pipefail

REGION="${REGION:-us-east-1}"
NOMBRE="tienda-ia"
SG_NOMBRE="tienda-ia-sg"
TIPO="t3.small"
PUERTO=8501
AQUI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export AWS_PAGER=""

APLICAR=0; PUBLICO=0; ACCION=desplegar
for a in "$@"; do
  case "$a" in
    --aplicar) APLICAR=1 ;;
    --publico) PUBLICO=1 ;;
    --estado) ACCION=estado ;;
    --reanudar) ACCION=reanudar; APLICAR=1 ;;
    --detener) ACCION=detener; APLICAR=1 ;;
    *) echo "opcion desconocida: $a" >&2; exit 2 ;;
  esac
done

log(){ printf '\n==> %s\n' "$*"; }
hacer(){ if [ "$APLICAR" = 1 ]; then "$@"; else printf '    [simulado] %s\n' "$*"; fi; }
die(){ printf '\nERROR: %s\n' "$*" >&2; exit 1; }

aws sts get-caller-identity --query Arn --output text >/dev/null 2>&1 \
  || die "credenciales vencidas: copiar AWS Details -> AWS CLI a ~/.aws/credentials"

instancia(){
  aws ec2 describe-instances --region "$REGION" \
    --filters Name=tag:Name,Values="$NOMBRE" Name=instance-state-name,Values=pending,running,stopping,stopped \
    --query 'Reservations[0].Instances[0].InstanceId' --output text 2>/dev/null
}
ip_publica(){ aws ec2 describe-instances --region "$REGION" --instance-ids "$1" \
  --query 'Reservations[0].Instances[0].PublicIpAddress' --output text; }
responde(){ curl -s -o /dev/null -m 5 -w '%{http_code}' "http://$1:$PUERTO/_stcore/health" 2>/dev/null || true; }

VPC=$(aws ec2 describe-vpcs --region "$REGION" --filters Name=isDefault,Values=true --query 'Vpcs[0].VpcId' --output text)
SG=$(aws ec2 describe-security-groups --region "$REGION" \
      --filters Name=group-name,Values="$SG_NOMBRE" Name=vpc-id,Values="$VPC" \
      --query 'SecurityGroups[0].GroupId' --output text 2>/dev/null || echo None)
ID=$(instancia)

abrir_puerto(){
  local cidr
  if [ "$PUBLICO" = 1 ]; then cidr="0.0.0.0/0"; else cidr="$(curl -s https://checkip.amazonaws.com)/32"; fi
  # Se reemplazan las reglas anteriores: con el hotspot la IP propia cambia.
  local viejas
  viejas=$(aws ec2 describe-security-groups --region "$REGION" --group-ids "$SG" \
            --query 'SecurityGroups[0].IpPermissions' --output json)
  if [ "$viejas" != "[]" ]; then
    hacer aws ec2 revoke-security-group-ingress --region "$REGION" --group-id "$SG" --ip-permissions "$viejas" >/dev/null
  fi
  hacer aws ec2 authorize-security-group-ingress --region "$REGION" --group-id "$SG" \
    --protocol tcp --port "$PUERTO" --cidr "$cidr" >/dev/null
  echo "    puerto $PUERTO abierto a $cidr"
}

esperar(){
  local ip
  aws ec2 wait instance-running --region "$REGION" --instance-ids "$1"
  ip=$(ip_publica "$1")
  echo "    IP: $ip  (la primera instalacion tarda 5-10 min)"
  for _ in $(seq 1 90); do
    [ "$(responde "$ip")" = 200 ] && { echo "    responde: http://$ip:$PUERTO"; return 0; }
    sleep 10
  done
  die "no respondio en 15 min. Log en la EC2: /var/log/tienda-ia.log (entrar por SSM)"
}

case "$ACCION" in
  estado)
    [ "$ID" != "None" ] || die "no hay instancia $NOMBRE"
    ESTADO=$(aws ec2 describe-instances --region "$REGION" --instance-ids "$ID" \
              --query 'Reservations[0].Instances[0].State.Name' --output text)
    IP=$(ip_publica "$ID")
    echo "$ID  $ESTADO  ${IP}  health=$(responde "$IP")"
    exit 0 ;;
  detener)
    [ "$ID" != "None" ] || die "no hay instancia $NOMBRE"
    aws ec2 stop-instances --region "$REGION" --instance-ids "$ID" >/dev/null
    echo "deteniendo $ID"
    exit 0 ;;
  reanudar)
    [ "$ID" != "None" ] || die "no hay instancia $NOMBRE: correr con --aplicar"
    aws ec2 start-instances --region "$REGION" --instance-ids "$ID" >/dev/null
    abrir_puerto
    esperar "$ID"
    exit 0 ;;
esac

[ "$APLICAR" = 1 ] || echo "SIMULACION: no se cambia nada. Agregar --aplicar para ejecutar."

log "Secretos al Parameter Store (/tienda-ia/*)"
[ -f "$AQUI/.env" ] || die "falta .env"
for clave in GROQ_API_KEY DUENO_CLAVE_HASH; do
  valor=$(grep -E "^$clave=" "$AQUI/.env" | head -1 | cut -d= -f2-)
  [ -n "$valor" ] || die "$clave vacio en .env (la clave del dueño se crea con: uv run python acceso.py)"
  hacer aws ssm put-parameter --region "$REGION" --name "/tienda-ia/$clave" --type SecureString \
    --value "$valor" --overwrite >/dev/null
  echo "    /tienda-ia/$clave (${#valor} caracteres, valor no mostrado)"
done

log "Security group $SG_NOMBRE"
if [ "$SG" = "None" ] || [ -z "$SG" ]; then
  if [ "$APLICAR" = 1 ]; then
    SG=$(aws ec2 create-security-group --region "$REGION" --group-name "$SG_NOMBRE" \
          --description "Streamlit 8501, sin SSH (acceso por SSM)" --vpc-id "$VPC" --query GroupId --output text)
    echo "    creado $SG"
  else
    echo "    [simulado] crear $SG_NOMBRE en $VPC"; SG="sg-simulado"
  fi
else
  echo "    ya existia $SG"
fi
if [ "$SG" != "sg-simulado" ]; then abrir_puerto; fi

log "EC2 $NOMBRE"
if [ "$ID" != "None" ] && [ -n "$ID" ]; then
  echo "    ya existia $ID"
  [ "$APLICAR" = 1 ] && esperar "$ID"
  exit 0
fi
AMI=$(aws ssm get-parameter --region "$REGION" \
       --name /aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64 \
       --query Parameter.Value --output text)
SUBNET=$(aws ec2 describe-subnets --region "$REGION" --filters Name=vpc-id,Values="$VPC" \
          --query 'Subnets[?MapPublicIpOnLaunch==`true`]|[0].SubnetId' --output text)
echo "    $TIPO · AMI $AMI · subred $SUBNET · 20 GB"
if [ "$APLICAR" = 1 ]; then
  ID=$(aws ec2 run-instances --region "$REGION" --image-id "$AMI" --instance-type "$TIPO" \
        --subnet-id "$SUBNET" --security-group-ids "$SG" --associate-public-ip-address \
        --iam-instance-profile Name=LabInstanceProfile \
        --metadata-options HttpTokens=required \
        --block-device-mappings '[{"DeviceName":"/dev/xvda","Ebs":{"VolumeSize":20,"VolumeType":"gp3","DeleteOnTermination":true}}]' \
        --user-data "file://$AQUI/aws-user-data.sh" \
        --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=$NOMBRE}]" \
        --query 'Instances[0].InstanceId' --output text)
  echo "    creada $ID"
  esperar "$ID"
else
  echo "    [simulado] run-instances con aws-user-data.sh"
fi
