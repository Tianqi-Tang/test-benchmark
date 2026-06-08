FROM node:24-alpine

WORKDIR /app

COPY frontend/package.json frontend/pnpm-lock.yaml* ./
RUN corepack enable && pnpm install --frozen-lockfile

COPY frontend ./
RUN VITE_BASE_PATH=/test-benchmark/ pnpm build

EXPOSE 80

CMD ["pnpm", "preview", "--host", "0.0.0.0", "--port", "80"]
