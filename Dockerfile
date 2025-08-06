# Use official python base image
FROM python:3.12.2-slim

# Set working dir
WORKDIR /app

# Copy dep files and install them
COPY requirements.txt ./
RUN pip install --upgrade pip && pip install -r requirements.txt

# Copy all source code
COPY . .

# Expose streamlit's default port
EXPOSE 8501

# Run app
CMD ["streamlit", "run", "streamlit_app.py", "--server.port=8501", "--server.address=0.0.0.0"]