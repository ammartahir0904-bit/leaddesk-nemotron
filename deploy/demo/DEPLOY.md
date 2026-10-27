# Hosting the public demo

The demo image serves fictional data with internet actions switched off. Only AI rewording (NVIDIA Nemotron on Nebius
Token Factory) reaches out, capped at `LEADDESK_DEMO_AI_PER_HOUR` calls per hour (default 30) so judges cannot use up your credits.

## 1. A server
Create a small Linux virtual machine on **Nebius AI Cloud** (CPU only is enough: 2 vCPU and 4 GB RAM), with Ubuntu, a public
IP address and ports 80 and 443 open. Install Docker on it:
```
curl -fsSL https://get.docker.com | sh
```

## 2. The image
Either build it on the server from the public repository:
```
git clone <public-repo-url> leaddesk && cd leaddesk
docker build -t leaddesk-demo .
```
or build it on your computer and copy it over (`docker save leaddesk-demo | gzip > leaddesk-demo.tar.gz`, then `docker load` on the server).

## 3. Run it behind HTTPS
Point a domain (or a free name such as `<server-ip>.sslip.io`) at the server. Then:
```
docker network create demo
docker run -d --name leaddesk --restart unless-stopped --network demo \
  -e NEBIUS_API_KEY="<your Token Factory key>" -e LEADDESK_PUBLIC_HOST="<your-domain>" leaddesk-demo
docker run -d --name caddy --restart unless-stopped --network demo -p 80:80 -p 443:443 \
  caddy:2 caddy reverse-proxy --from <your-domain> --to leaddesk:8765
```
Caddy gets the HTTPS certificate automatically. Open `https://<your-domain>`: the lock screen fills in the demo key.

## 4. Choose the Nemotron model
Add `-e LEADDESK_DEMO_MODEL="<exact model id>"` to the `docker run` above so every restart uses it. To find the exact id,
unlock the demo and open **AI models and hardware**: it lists the NVIDIA models your key can use. (You can also pick one
there; that choice lasts until the next restart, which resets the fictional data.)

## Notes
- The key is passed as an environment variable, never baked into the image. Do not commit it.
- `docker logs leaddesk` shows a note if `NEBIUS_API_KEY` is missing.
- Take the demo down after judging (15 December 2026): `docker rm -f leaddesk caddy`.
