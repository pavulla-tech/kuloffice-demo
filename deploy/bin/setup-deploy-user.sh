#!/bin/sh
# Once, as root, on the server: the account CI deploys through.
#
#   sudo sh bin/setup-deploy-user.sh [user]      (default: kulpay-deploy)
#
# - The user, in the docker group, with the password you type (the one in
#   GitHub's DEPLOY_PASSWORD), or a long random one if you just press Enter
#   (printed once: put it in DEPLOY_PASSWORD).
# - A group shared with whoever owns this checkout, so both can run make and
#   the deploy tool on the same files (.env becomes group-readable: 660).
# - sshd: password login for that user only, forced to bin/kulpay-ssh, with no
#   shell, TTY or forwarding. Docker access is root-equivalent; the forced
#   command is what keeps the password from being more than a deploy button.
# - fail2ban, if it isn't there.
#
# Safe to run again: it sets the password again and rewrites the sshd snippet.
set -eu
[ "$(id -u)" = 0 ] || { echo "run as root (sudo)" >&2; exit 1; }
user=${1:-kulpay-deploy}
group=kulpay
deploy_dir=$(cd "$(dirname "$0")/.." && pwd)
repo=$(cd "$deploy_dir/.." && pwd)
owner=$(stat -c %U "$repo")

# Docker's group: the docker-ce package creates it; snap or hand installs may
# not. The socket is handed to it now, with no daemon restart (that would stop
# every container on the server); Docker does the same itself on its next
# start, once the group exists.
getent group docker > /dev/null || { groupadd --system docker; echo "created the docker group"; }
sock=$(docker context inspect -f '{{.Endpoints.docker.Host}}' 2> /dev/null | sed 's|^unix://||')
[ -S "${sock:-}" ] || sock=/var/run/docker.sock
if [ -S "$sock" ] && [ "$(stat -c %G "$sock")" != docker ]; then
  chgrp docker "$sock" && chmod 660 "$sock"
  echo "gave the docker group access to $sock"
fi

getent group "$group" > /dev/null || groupadd "$group"
id "$user" > /dev/null 2>&1 || useradd -m -s /bin/bash "$user"
usermod -aG docker,"$group" "$user"
[ "$owner" = root ] || usermod -aG "$group" "$owner"

# The checkout: group-owned and group-writable, new files inherit the group.
chgrp -R "$group" "$repo"
chmod -R g+rwX "$repo"
find "$repo" -type d -exec chmod g+s {} +
for f in .env kuloffice.env kulportal.env; do [ ! -f "$deploy_dir/$f" ] || chmod 660 "$deploy_dir/$f"; done
git -C "$repo" config core.sharedRepository group
su - "$user" -c "git config --global --add safe.directory '$repo'"

printf 'Password for %s (the DEPLOY_PASSWORD secret; Enter to generate one): ' "$user"
stty -echo 2> /dev/null || true; read -r password || true; stty echo 2> /dev/null || true; echo
generated=no
if [ -z "$password" ]; then
  password=$(head -c 32 /dev/urandom | base64 | tr -d '=+/' | cut -c1-40); generated=yes
fi
echo "$user:$password" | chpasswd

cat > /etc/ssh/sshd_config.d/kulpay-deploy.conf << EOF
# KulPay CI: password login, forced to the deploy tool (bin/setup-deploy-user.sh).
Match User $user
    PasswordAuthentication yes
    KbdInteractiveAuthentication no
    ForceCommand $deploy_dir/bin/kulpay-ssh
    PermitTTY no
    AllowTcpForwarding no
    AllowAgentForwarding no
    AllowStreamLocalForwarding no
    X11Forwarding no
    PermitTunnel no
Match all
EOF
grep -Eq '^\s*Include\s+/etc/ssh/sshd_config.d/\*\.conf' /etc/ssh/sshd_config ||
  echo "warning: /etc/ssh/sshd_config doesn't include sshd_config.d/*.conf; add the snippet's lines to it" >&2
sshd -t
systemctl reload ssh 2> /dev/null || systemctl reload sshd

if ! command -v fail2ban-client > /dev/null; then
  if command -v apt-get > /dev/null; then
    # Non-interactive: needrestart's "restart which services?" would wait,
    # unseen, behind the redirect.
    DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=l NEEDRESTART_SUSPEND=1 \
      apt-get install -y -q fail2ban > /dev/null && systemctl enable --now fail2ban > /dev/null 2>&1 || true
    echo "fail2ban installed (its sshd jail is on by default)"
  else
    echo "warning: install fail2ban yourself" >&2
  fi
fi

host_key=$(cut -d' ' -f1,2 /etc/ssh/ssh_host_ed25519_key.pub)
echo
echo "Done. GitHub's organisation secrets (CICD.md):"
echo "  DEPLOY_USER          $user"
if [ "$generated" = yes ]; then
  echo "  DEPLOY_PASSWORD      $password"
  echo "                       (not shown again; run this script again for another)"
else
  echo "  DEPLOY_PASSWORD      the one you typed"
fi
echo "  DEPLOY_KNOWN_HOSTS   <DEPLOY_HOST> $host_key"
echo "                       (with DEPLOY_HOST's exact value in front)"
echo "Check: GitHub → kuloffice-demo → Actions → Server → status"

