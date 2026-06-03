# P7f -- Neon Odoo image: stock odoo:17 + the certificate display fonts
# baked in. wkhtmltopdf (0.12.6, patched Qt) ignores @font-face in every
# form and renders only OS-installed fonts via fontconfig, so the
# Design-A certificate's Fraunces / Spline Sans / Spline Sans Mono faces
# must live in the image. Baking them (rather than installing into a
# running container) means they survive every
# `docker compose up --force-recreate` -- the whole point, since certs
# are durable documents. See deploy/fonts/ + addons/neon_training/report.
FROM odoo:17

# fontconfig's cache (/var/cache/fontconfig) is root-owned and the stock
# image's runtime user is `odoo`; flip to root to install + build the
# cache, then restore `odoo` so the container runs exactly as stock.
USER root
COPY deploy/fonts/*.ttf /usr/share/fonts/truetype/neon/
RUN fc-cache -f /usr/share/fonts/truetype/neon
USER odoo
