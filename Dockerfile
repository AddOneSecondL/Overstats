FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /opt
COPY requirements.txt /opt/requirements.txt
RUN pip install --no-cache-dir -r /opt/requirements.txt
RUN pip install --no-cache-dir 'cos-python-sdk-v5>=1.9,<2'
COPY . /opt/overstats
RUN python /opt/overstats/scf_prepare_assets.py
EXPOSE 9000
CMD ["python", "/opt/overstats/scf_bootstrap.py"]
