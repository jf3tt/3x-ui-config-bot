# Use an official lightweight Python image.
FROM python:3.10-slim

# Set environment variables to ensure stdout and stderr are flushed immediately
ENV PYTHONUNBUFFERED=1

# Set the working directory
WORKDIR /app

# Copy the requirements file and install dependencies
COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

# Copy the rest of the application code
COPY . .

# Expose any necessary ports (optional, if your bot listens on a port)
# EXPOSE 8080

# Set the entrypoint to run the bot
CMD ["python", "bot.py"]
