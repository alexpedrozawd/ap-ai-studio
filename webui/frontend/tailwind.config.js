/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  // O Bootstrap ja fornece o CSS reset base - desligamos o preflight do Tailwind pra
  // eles nao brigarem entre si. Tailwind fica so' como utilitario de espacamento/layout
  // por cima dos componentes do react-bootstrap.
  corePlugins: {
    preflight: false,
  },
  theme: {
    extend: {},
  },
  plugins: [],
}
