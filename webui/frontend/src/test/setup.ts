import "@testing-library/jest-dom/vitest";

// jsdom nao implementa APIs de layout/scroll (por design - nao faz render visual de
// verdade). JobLogPanel usa scrollTo() pra manter o log rolado pro final; sem esse
// polyfill, todo teste que renderiza esse componente quebra por um motivo que nao tem
// nada a ver com o comportamento sendo testado.
if (!Element.prototype.scrollTo) {
  Element.prototype.scrollTo = () => {};
}
