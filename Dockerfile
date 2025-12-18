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
# Copy the rest of the application
COPY src/ src/

# Note: .env is ignored. Railway Config Variables are used in production.
# Local dev uses .env via python-dotenv loading.


# Create logs directory
RUN mkdir logs

# Run the bot
CMD ["python", "src/main.py"]
