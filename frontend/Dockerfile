FROM node:24-alpine

WORKDIR /app

# Install pnpm
RUN corepack enable && corepack prepare pnpm@12.4.1 --activate

# Copy package files
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./

# Install dependencies
RUN pnpm install --frozen-lockfile

# Copy app
COPY . .

# Build (optional, for production)
# RUN pnpm run build

# Run dev server
CMD ["pnpm", "run", "dev"]
