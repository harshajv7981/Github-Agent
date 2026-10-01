#!/bin/zsh

export ANTHROPIC_BASE_URL="http://localhost:20128/v1"
export ANTHROPIC_AUTH_TOKEN="sk-2995805eece764c5-d90f93-40474b82"
export ANTHROPIC_API_KEY=""
export ANTHROPIC_MODEL="antigravity/claude-sonnet-4-6"
export ANTHROPIC_SMALL_FAST_MODEL="antigravity/claude-sonnet-4-6"
export CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1

claude "$@"
