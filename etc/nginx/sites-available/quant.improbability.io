server {
    listen 80;
    server_name quant.improbability.io;  // Update your Hostname

    location ^~ /.well-known/acme-challenge/ {
        allow all;
        root /var/www/html;
        try_files $uri =404;
    }

    # Redirect all HTTP traffic to HTTPS
    location / {
        return 301 https://$server_name$request_uri;
    }

}

server {
    listen 443 ssl;
    server_name quant.improbability.io;  // Update your Hostname

    ssl_certificate /etc/letsencrypt/live/quant.improbability.io/fullchain.pem;    // Update the SSL Cert files
    ssl_certificate_key /etc/letsencrypt/live/quant.improbability.io/privkey.pem;  // Update the SSL Cert files

    # Enable Gzip compression
    gzip on;
    gzip_types text/plain text/css application/json application/javascript text/xml application/xml application/xml+rss text/javascript application/x-font-ttf font/opentype application/vnd.ms-fontobject image/svg+xml;
    gzip_proxied any;
    gzip_vary on;
    gzip_min_length 256;
    gzip_comp_level 5;
    gzip_disable "msie6";

    location / {
        proxy_pass http://localhost:8001/;
        proxy_set_header Host $http_host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-Host $host;

        # Add caching headers for dynamic content
        add_header Cache-Control "no-store";
    }

    location ~* \.(js|css|png|jpg|jpeg|gif|ico|svg)$ {
        proxy_pass http://localhost:8001;
        proxy_set_header Host $http_host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-Host $host;

        expires 1y;
        add_header Cache-Control "public, max-age=31536000, immutable";
    }

    location ~* \.(html|htm)$ {
        proxy_pass http://localhost:8001;
        proxy_set_header Host $http_host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-Host $host;

        expires 1h;
        add_header Cache-Control "public, max-age=3600";
    }

    # Security headers
    add_header X-Frame-Options SAMEORIGIN;
    add_header X-Content-Type-Options nosniff;
    add_header X-XSS-Protection "1; mode=block";
    add_header Referrer-Policy "no-referrer-when-downgrade";
    add_header Content-Security-Policy "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self'";
}

