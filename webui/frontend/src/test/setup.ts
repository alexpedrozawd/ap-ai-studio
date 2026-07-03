import "@testing-library/jest-dom/vitest";

// jsdom nao implementa APIs de layout/scroll (por design - nao faz render visual de
// verdade). JobLogPanel usa scrollTo() pra manter o log rolado pro final; sem esse
// polyfill, todo teste que renderiza esse componente quebra por um motivo que nao tem
// nada a ver com o comportamento sendo testado.
if (!Element.prototype.scrollTo) {
  Element.prototype.scrollTo = () => {};
}

// jsdom tambem nao implementa URL.createObjectURL/revokeObjectURL (faz sentido - nao
// ha um blob real por tras). BeforeAfterCompare usa isso pra mostrar o arquivo
// original no navegador antes do upload terminar; sem esse polyfill, qualquer teste
// que chegue no estado "job concluido" quebra por um TypeError que nao tem nada a ver
// com o que esta sendo testado.
if (!URL.createObjectURL) {
  URL.createObjectURL = () => "blob:mock-url";
}
if (!URL.revokeObjectURL) {
  URL.revokeObjectURL = () => {};
}
