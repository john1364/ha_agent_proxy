FROM python:3.12-alpine
COPY proxy.py /proxy.py
CMD ["python3", "/proxy.py"]