FROM nginx:1.27-alpine

ENV BACKEND_PORT=2288
ENV NGINX_CLIENT_MAX_BODY_SIZE=10G

COPY nginx.conf /etc/nginx/templates/default.conf.template
