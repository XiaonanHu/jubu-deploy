FROM python:3.10-slim

WORKDIR /app

COPY . .
RUN pip install -e .

CMD ["python", "-m", "jubu_chat"] 