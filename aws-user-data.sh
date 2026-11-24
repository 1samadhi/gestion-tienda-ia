#!/bin/bash
# Arranque de la EC2 (Amazon Linux 2023). Los secretos no viajan aqui: se leen
# del Parameter Store con el rol de la instancia.
set -euxo pipefail
exec > >(tee /var/log/tienda-ia.log) 2>&1

REPO="https://github.com/1samadhi/gestion-tienda-ia.git"
RAMA="aws"
DIR="/opt/tienda-ia"
TOKEN=$(curl -s -X PUT http://169.254.169.254/latest/api/token -H "X-aws-ec2-metadata-token-ttl-seconds: 300")
REGION=$(curl -s -H "X-aws-ec2-metadata-token: $TOKEN" http://169.254.169.254/latest/meta-data/placement/region)

# 1 GB de swap: con 2 GB de RAM la instalacion de dependencias queda justa.
if [ ! -f /swapfile ]; then
  dd if=/dev/zero of=/swapfile bs=1M count=1024 && chmod 600 /swapfile
  mkswap /swapfile && swapon /swapfile && echo "/swapfile swap swap defaults 0 0" >> /etc/fstab
fi

dnf install -y git
id tienda >/dev/null 2>&1 || useradd --system --create-home --home-dir /home/tienda tienda
curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin UV_NO_MODIFY_PATH=1 sh

[ -d "$DIR/.git" ] || git clone --branch "$RAMA" "$REPO" "$DIR"
git -C "$DIR" pull --ff-only
chown -R tienda:tienda "$DIR"

parametro() { aws ssm get-parameter --region "$REGION" --name "$1" --with-decryption --query Parameter.Value --output text; }
umask 077
cat > "$DIR/.env" <<EOF
GROQ_API_KEY=$(parametro /tienda-ia/GROQ_API_KEY)
DUENO_CLAVE_HASH=$(parametro /tienda-ia/DUENO_CLAVE_HASH)
MEMORIA_CREW=false
LANGSMITH_TRACING=false
EOF
chown tienda:tienda "$DIR/.env"

# Sin el grupo "memoria": no se instala torch.
sudo -u tienda -H bash -c "cd $DIR && uv sync --frozen --no-default-groups && [ -f tienda.db ] || uv run python db.py"

cat > /etc/systemd/system/tienda-ia.service <<EOF
[Unit]
Description=Gestion de Tienda IA (Streamlit)
After=network-online.target

[Service]
User=tienda
WorkingDirectory=$DIR
ExecStart=/usr/local/bin/uv run --frozen --no-default-groups streamlit run app.py --server.port 8501 --server.address 0.0.0.0 --server.headless true
Restart=on-failure

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable --now tienda-ia
