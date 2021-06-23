FROM python:3.8

ADD main.py .

RUN pip install boto3 ratelimit requests

CMD [ "python", "./main.py" ]