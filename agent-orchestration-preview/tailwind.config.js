/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  // 关闭 preflight，避免与 MUI 的样式重置相互覆盖
  corePlugins: {
    preflight: false,
  },
  theme: {
    extend: {
      colors: {
        primary: '#3B82F6',
        secondary: '#10B981',
        success: '#22C55E',
        warning: '#F59E0B',
        error: '#EF4444',
        'bg-default': '#0F172A',
        'bg-paper': '#1E293B',
        divider: '#334155',
      },
      borderRadius: {
        DEFAULT: '8px',
      },
    },
  },
  plugins: [],
};
