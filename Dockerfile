FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DATA_DIR=/data

WORKDIR /app

# rasm ichidagi yozuvni o'qish (utils/media_text.py): Tesseract va o'zbek (lotin, kirill), rus, ingliz tillari
RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-uzb tesseract-ocr-uzb-cyrl tesseract-ocr-rus \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# root bo'lmagan foydalanuvchi; bot.db shu papkada saqlanadi, volume sifatida ulanadi
RUN useradd --create-home app && mkdir /data && chown app:app /data
USER app
VOLUME /data
# webhook rejimida bot shu portda tinglaydi (polling rejimida ishlatilmaydi)
EXPOSE 8080

CMD ["python", "main.py"]
