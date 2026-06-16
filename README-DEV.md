# Development Guide

This document describes the development environment setup and best practices for the Laguna AI project.

## Local Setup
1. Copy `.env.example` to `.env` and fill in the values:
   ```bash
   cp .env.example .env
   ```
2. Start the development environment with Docker:
   ```bash
   docker-compose --profile dev up -d
   ```
3. Access the backend services at `http://localhost:8001`.
