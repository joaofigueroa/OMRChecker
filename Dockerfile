FROM tiangolo/uvicorn-gunicorn-fastapi:python3.7

COPY ./app /app
WORKDIR /app

RUN apt-get update -y
RUN apt install libgl1-mesa-glx -y
RUN apt-get install 'ffmpeg'\
  'libsm6'\
  'libxext6'  -y
RUN pip3 install --upgrade pip

RUN pip3 install -r requirements.txt
