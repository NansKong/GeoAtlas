/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: ["class"],
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["Inter", "system-ui", "sans-serif"],
      },
      colors: {
        // GeoAtlas brand palette
        geo: {
          50:  "#f0f4ff",
          100: "#dbe4ff",
          200: "#b3c6ff",
          300: "#85a6ff",
          400: "#567eff",
          500: "#2f57f5",
          600: "#1e3fd4",
          700: "#182faa",
          800: "#152387",
          900: "#0f1a62",
        },
        // Sentiment colors
        bull: "#10b981",  // green — positive
        bear: "#ef4444",  // red — negative
        neutral: "#6b7280",
        // Card background
        surface: {
          DEFAULT: "#ffffff",
          dark: "#111111",
          muted: "#f9fafb",
        },
      },
      borderRadius: {
        "2xl": "1rem",
        "3xl": "1.5rem",
        pin: "1.25rem",
      },
      boxShadow: {
        pin: "0 2px 8px rgba(0,0,0,0.08), 0 0 0 0.5px rgba(0,0,0,0.06)",
        "pin-hover": "0 8px 24px rgba(0,0,0,0.14), 0 0 0 0.5px rgba(0,0,0,0.08)",
      },
      keyframes: {
        "fade-up": {
          from: { opacity: "0", transform: "translateY(12px)" },
          to:   { opacity: "1", transform: "translateY(0)" },
        },
        shimmer: {
          "0%":   { backgroundPosition: "-400px 0" },
          "100%": { backgroundPosition: "400px 0" },
        },
      },
      animation: {
        "fade-up": "fade-up 0.3s ease-out forwards",
        shimmer: "shimmer 1.4s linear infinite",
      },
    },
  },
  plugins: [],
};
