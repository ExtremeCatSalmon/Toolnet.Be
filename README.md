# Grape API 실행 가이드

이 문서는 Grape API를 로컬에서 돌리기 위한 가이드입니다.

---

## 1. 필수 패키지 설치 pip/linux(ubuntu) 명령어

프로젝트 실행에 필요한 Python 라이브러리를 설치해야 합니다. 코드는 다음과 같습니다.

```bash
pip install fastapi uvicorn pydantic pydantic-settings PyJWT redis email-validator
```

```bash
sudo apt update
sudo apt install redis-server -y
sudo systemctl start redis-server
sudo systemctl enable redis-server
redis-cli ping
```

여기에서 enable redis-server는 선택이고, redis-cli ping이라고 할 때, PONG이라고 뜨면 정상입니다.

## 2. env 설정

코드에서 env 파일의 환경 변수를 읽어오고 있으므로, main.py와 **동일한 폴더**에 .env를 넣어주세요.

```env
DB_NAME=grape.db
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_DB=0
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your_email@gmail.com
SMTP_PASSWORD=your_app_password
JWT_SECRET=your_super_secret_key_here
JWT_ALGORITHM=HS256
JWT_EXPIRATION_MINUTES=1440
```

여기에서 SMTP_USER, SMTP_PASSWORD는 저기 계정 주인분한테 가시고, JWT_SECRET은 저한테 오면 알려드리겠습니다.

## 3. 서버 실행

위의 모든 설정이 완료되었다면 다음 명령어를 이용해서 Fast API 서버를 실행합니다.

```bash
uvicorn main:app --reload
```

## Postman
저는 wi_gen_5G_51입니다.
ip도 저한테 오면 알려드리겠습니다.