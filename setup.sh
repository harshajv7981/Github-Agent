#!/bin/bash

set -e

echo "🔧 Setting up Patchwork - AI Open-Source Contribution Agent"
echo ""

# Check for required tools
echo "✓ Checking prerequisites..."

if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 is required but not installed."
    exit 1
fi

if ! command -v node &> /dev/null; then
    echo "❌ Node.js is required but not installed."
    exit 1
fi

if ! command -v psql &> /dev/null; then
    echo "⚠️  PostgreSQL not found. You'll need to install it:"
    echo "   macOS: brew install postgresql@16"
    echo "   Ubuntu: sudo apt-get install postgresql"
    echo ""
fi

# Setup Python virtual environment
echo ""
echo "📦 Setting up Python environment..."
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
fi

source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# Setup environment file
echo ""
echo "⚙️  Setting up environment configuration..."
if [ ! -f ".env" ]; then
    cat > .env <<'EOF'
GITHUB_TOKEN=
DATABASE_URL=postgresql+asyncpg://localhost:5432/patchwork
OLLAMA_HOST=http://127.0.0.1:11434
OLLAMA_MODEL=qwen3.5:9b
OLLAMA_CODING_MODEL=qwen3.5:9b
OLLAMA_REVIEW_MODEL=qwen3.5:9b
SANDBOX_RUNTIME=process
SANDBOX_DOCKER_IMAGE=patchwork-sandbox:latest
GITHUB_WEBHOOK_SECRET=
EOF
    echo "✓ Created .env with local defaults"
    echo "⚠️  Edit .env if your database or Ollama configuration differs"
else
    echo "✓ .env file already exists"
fi

# Setup database
echo ""
echo "🗄️  Setting up database..."
echo "This will create a PostgreSQL database named 'patchwork'"
echo "Default credentials: postgres:postgres"
echo ""
read -p "Do you want to create the database now? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    createdb patchwork -U postgres || echo "Database may already exist"
    echo "✓ Database setup complete"
fi

# Setup frontend
echo ""
echo "🎨 Setting up frontend..."
cd frontend
npm install
cd ..

# Check Ollama
echo ""
echo "🤖 Checking Ollama..."
if command -v ollama &> /dev/null; then
    echo "✓ Ollama is installed"
    if ollama list | grep -q "qwen2.5-coder:7b"; then
        echo "✓ qwen2.5-coder:7b model is available"
    else
        echo "⚠️  qwen2.5-coder:7b model not found"
        echo "   Pull it with: ollama pull qwen2.5-coder:7b"
    fi
else
    echo "⚠️  Ollama not found. Install from: https://ollama.ai"
fi

echo ""
echo "✅ Setup complete!"
echo ""
echo "📋 Next steps:"
echo "   1. Edit .env and add your GITHUB_TOKEN (optional but recommended)"
echo "   2. Start PostgreSQL if not running"
echo "   3. Start the API: uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port 8000"
echo "   4. Start the frontend: cd frontend && npm run dev"
echo "   5. Open http://localhost:5173"
echo ""
