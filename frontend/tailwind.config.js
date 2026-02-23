/** @type {import('tailwindcss').Config} */
export default {
  darkMode: 'class',
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
    "node_modules/flowbite-react/lib/esm/**/*.js",
  ],
  theme: {
    extend: {
      screens: {
        'xl-custom': '1650px', // Custom breakpoint for hamburger menu
      },
      colors: {
        // Logo-inspired purple (shield) – primary actions, links, focus
        purple: {
          50: '#f5f0fa',
          100: '#ebe0f5',
          200: '#d4c2eb',
          300: '#b89ade',
          400: '#9469c9',
          500: '#6b30a8',
          600: '#520474',
          700: '#4d0c7d',
          800: '#33055d',
          900: '#21043a',
          950: '#14051f',
        },
        // Logo-inspired gold (emblem) – accents, badges, highlights
        brand: {
          gold: {
            50: '#faf8ed',
            100: '#f5f0d4',
            200: '#ebe0a8',
            300: '#dfcc73',
            400: '#d0b84a',
            500: '#c3b042',
            600: '#a17904',
            700: '#8c842c',
            800: '#7f7025',
            900: '#544c1c',
          },
        },
      },
    },
  },
  plugins: [
    require('flowbite/plugin')
  ],
};
