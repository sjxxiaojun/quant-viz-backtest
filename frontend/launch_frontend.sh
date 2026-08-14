#!/bin/bash
export PATH=$PATH:~/.local/bin
cd ./frontend
exec ~/.local/bin/npm run dev -- --force >> ./frontend/frontend.log 2>&1
