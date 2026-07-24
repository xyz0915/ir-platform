// ESLint 配置文件 — Vue 3 + Vite 最小规则集
// 当前为占位配置，CI lint 阶段使用 echo 跳过。
// 安装 eslint + eslint-plugin-vue 后可启用实际检查：
//   npm install -D eslint eslint-plugin-vue

export default [
  {
    ignores: ["dist/**", "node_modules/**"],
  },
  {
    files: ["**/*.{js,vue}"],
    rules: {
      // 基础规则（预留）
      "no-unused-vars": "warn",
      "no-console": "warn",
    },
  },
];
