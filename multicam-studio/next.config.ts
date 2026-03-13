import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  env: {
    NEXT_PUBLIC_BUILD_NUM: process.env.BUILD_NUM || '0',
  },
};

export default nextConfig;
