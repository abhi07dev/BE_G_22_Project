FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends libglib2.0-0 libgl1 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV OPENCV_FFMPEG_CAPTURE_OPTIONS="rtsp_transport;tcp"
CMD python -m cv_service.worker --cam cam01 --url ${CAM01_URL} --calib calib/cam01.json
