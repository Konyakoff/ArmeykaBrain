# Инструкция по деплою ArmeykaBrain на сервер с Nginx

Эта инструкция описывает, как настроить Nginx на вашем сервере (`72.56.124.154`), чтобы он принимал запросы с домена `armeykabrain.net` и перенаправлял их на Docker-контейнер с FastAPI-приложением (порт 8000).

## Шаг 1. Настройка домена в Cloudflare

1. Зайдите в панель управления **Cloudflare**.
2. Выберите ваш домен `armeykabrain.net`.
3. Перейдите в раздел **DNS** -> **Records**.
4. Убедитесь, что у вас есть A-запись, которая указывает на IP-адрес вашего сервера:
  - Type: `A`
  - Name: `@` (или `armeykabrain.net`)
  - Content: `72.56.124.154`
  - Proxy status: `Proxied` (оранжевое облако) или `DNS only` (серое). *Рекомендуется использовать Proxied для бесплатного SSL от Cloudflare.*
5. Добавьте аналогичную запись для поддомена `www` (опционально):
  - Type: `A` (или `CNAME`)
  - Name: `www`
  - Content: `72.56.124.154` (или `armeykabrain.net`)

## Шаг 2. Настройка сервера

Зайдите на сервер по SSH:

```bash
ssh root@72.56.124.154
```

Убедитесь, что Docker-контейнер запущен и работает на порту 8000. В папке с проектом (`/root/ArmeykaBrain`) выполните:

```bash
docker compose up -d --build
```

Проверьте, что приложение отвечает локально:

```bash
curl http://localhost:8000
```

*Вы должны увидеть HTML-код вашей новой главной страницы.*

## Шаг 3. Установка и настройка Nginx

Установите Nginx, если он еще не установлен:

```bash
apt update
apt install nginx -y
```

Создайте новый конфигурационный файл для вашего домена:

```bash
nano /etc/nginx/sites-available/armeykabrain.net
```

Вставьте туда следующий конфиг:

```nginx
server {
    listen 80;
    server_name armeykabrain.net www.armeykabrain.net;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Сохраните файл (`Ctrl+O`, `Enter`, `Ctrl+X`).

Активируйте конфигурацию, создав симлинк:

```bash
ln -s /etc/nginx/sites-available/armeykabrain.net /etc/nginx/sites-enabled/
```

Проверьте конфигурацию Nginx на наличие ошибок:

```bash
nginx -t
```

*Ожидаемый результат: `syntax is ok` и `test is successful`.*

Перезапустите Nginx, чтобы применить изменения:

```bash
systemctl restart nginx
```

## Шаг 4. Настройка SSL (HTTPS) - если Cloudflare в режиме "DNS only"

Если в Cloudflare у вас стоит **"DNS only" (серое облачко)**, вам нужно получить бесплатный SSL-сертификат через Certbot (Let's Encrypt):

1. Установите Certbot:

```bash
apt install certbot python3-certbot-nginx -y
```

1. Выпустите сертификат:

```bash
certbot --nginx -d armeykabrain.net -d www.armeykabrain.net
```

Следуйте инструкциям на экране (укажите email, согласитесь с правилами). Certbot автоматически обновит ваш конфиг Nginx для работы по HTTPS.

*Примечание: Если в Cloudflare включено "Proxied" (оранжевое облако), Cloudflare сам обеспечивает SSL, и этот шаг можно пропустить. Перейдите в Cloudflare -> SSL/TLS и убедитесь, что режим шифрования установлен на **Flexible** (или Full, если на сервере стоит свой сертификат).*

## Итог

Теперь при переходе по адресу `http://armeykabrain.net` (или `https://armeykabrain.net`) вы увидите ваш новый веб-интерфейс, который полностью заменяет Telegram-бота!