#!/bin/bash
set -e

echo "🚀 Starting MAGI System AI-driven setup..."

# 1. Backend setup (Python)
echo "📦 Setting up backend dependencies with uv..."
if command -v uv > /dev/null; then
    uv sync
else
    echo "❌ uv is not installed. Please install it first: https://github.com/astral-sh/uv"
    exit 1
fi

# 2. Frontend setup (Node.js)
echo "📦 Setting up frontend dependencies..."
if [ -d "frontend" ]; then
    (
        cd frontend
        if command -v npm > /dev/null; then
            npm install
        else
            echo "⚠️ npm is not installed. Skipping frontend setup."
        fi
    )
fi

# 3. Environment variables
echo "🔑 Setting up environment variables..."
if [ ! -f ".env" ]; then
    if [ -f ".env.example" ]; then
        cp .env.example .env
        echo "✅ Created .env from .env.example (Please fill in your API keys)"
    else
        touch .env
        echo "✅ Created empty .env"
    fi
else
    echo "ℹ️ .env already exists."
fi

# 4. Verification
echo "🔍 Verifying installation..."
uv run magi --version || echo "⚠️ magi command failed. Check your installation."

echo "✨ Setup complete! AI is ready to work."
