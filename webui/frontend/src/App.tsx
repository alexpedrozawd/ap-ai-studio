import { Container, Nav, NavDropdown, Navbar } from "react-bootstrap";
import { NavLink, Route, Routes } from "react-router-dom";
import StatusPage from "./pages/StatusPage";
import FaceSwapPage from "./pages/FaceSwapPage";
import VideoPage from "./pages/VideoPage";
import InpaintPage from "./pages/InpaintPage";
import RemoveBgPage from "./pages/RemoveBgPage";
import VoicePage from "./pages/VoicePage";
import DubPage from "./pages/DubPage";
import DenoisePage from "./pages/DenoisePage";
import MusicPage from "./pages/MusicPage";
import MasterPage from "./pages/MasterPage";

// Fase A: Status + Trocar Rosto + Gerar Video.
// Fase B: + Editar Imagem, Remover Fundo, Voz, Dublagem, Limpar Audio, Musica,
// Masterizar - todas reaproveitando JobLogPanel/api.ts ja validados na Fase A.
// Navbar agrupada em dropdowns (Imagem/Audio) pra nao lotar de itens soltos.
export default function App() {
  return (
    <>
      <Navbar bg="dark" variant="dark" expand="md" className="mb-4">
        <Container>
          <Navbar.Brand>AP AI Studio</Navbar.Brand>
          <Navbar.Toggle aria-controls="main-nav" />
          <Navbar.Collapse id="main-nav">
            <Nav>
              <Nav.Link as={NavLink} to="/" end>
                Status
              </Nav.Link>
              <Nav.Link as={NavLink} to="/video">
                Gerar Video
              </Nav.Link>

              <NavDropdown title="Imagem" id="nav-imagem">
                <NavDropdown.Item as={NavLink} to="/rosto">
                  Trocar Rosto
                </NavDropdown.Item>
                <NavDropdown.Item as={NavLink} to="/editar">
                  Editar Imagem
                </NavDropdown.Item>
                <NavDropdown.Item as={NavLink} to="/semfundo">
                  Remover Fundo
                </NavDropdown.Item>
              </NavDropdown>

              <NavDropdown title="Áudio" id="nav-audio">
                <NavDropdown.Item as={NavLink} to="/voz">
                  Voz (TTS/Clonar)
                </NavDropdown.Item>
                <NavDropdown.Item as={NavLink} to="/dublar">
                  Dublagem
                </NavDropdown.Item>
                <NavDropdown.Item as={NavLink} to="/limpar">
                  Limpar Áudio
                </NavDropdown.Item>
                <NavDropdown.Item as={NavLink} to="/musica">
                  Música
                </NavDropdown.Item>
              </NavDropdown>

              <Nav.Link as={NavLink} to="/masterizar">
                Masterizar
              </Nav.Link>
            </Nav>
          </Navbar.Collapse>
        </Container>
      </Navbar>

      <Container className="pb-5">
        <Routes>
          <Route path="/" element={<StatusPage />} />
          <Route path="/rosto" element={<FaceSwapPage />} />
          <Route path="/video" element={<VideoPage />} />
          <Route path="/editar" element={<InpaintPage />} />
          <Route path="/semfundo" element={<RemoveBgPage />} />
          <Route path="/voz" element={<VoicePage />} />
          <Route path="/dublar" element={<DubPage />} />
          <Route path="/limpar" element={<DenoisePage />} />
          <Route path="/musica" element={<MusicPage />} />
          <Route path="/masterizar" element={<MasterPage />} />
        </Routes>
      </Container>
    </>
  );
}
