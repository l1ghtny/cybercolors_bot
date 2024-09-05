FROM python:3.12-alpine

WORKDIR /home/discord-bot/
RUN mkdir logs

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

ADD src ./src
COPY main.py .

CMD [ "python", "main.py" ]