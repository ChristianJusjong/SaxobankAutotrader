# Use an official Python runtime as a parent image
FROM python:3.13-slim

# Set the working directory in the container
WORKDIR /app

# Set environment variables
# PYTHONUNBUFFERED=1 ensures logs are printed immediately to stdout
ENV PYTHONUNBUFFERED=1

# Copy project files
# We copy requirements first to leverage Docker cache
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY src/ src/
COPY .env . 
# Note: .env is usually ignored in git, but for local docker build manual copy works.
# In Railway, you set variables in the Dashboard. 
# We copy it here just in case, but Railway variables override it.

# Create logs directory
RUN mkdir logs

# Run the bot
CMD ["python", "src/main.py"]
