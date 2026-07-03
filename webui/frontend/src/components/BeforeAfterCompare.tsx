import { useEffect, useState } from "react";
import { Col, Row } from "react-bootstrap";

interface BeforeAfterCompareProps {
  originalFile: File | null;
  resultUrl: string;
  isVideo?: boolean;
  beforeLabel?: string;
  afterLabel?: string;
}

// Comparacao antes/depois pras paginas que editam uma foto/video ja existente
// (troca de rosto, remover fundo, inpainting, upscale) - nao faz sentido pra
// geracao do zero (VideoPage/MusicPage), onde nao ha "antes".
export default function BeforeAfterCompare({
  originalFile,
  resultUrl,
  isVideo = false,
  beforeLabel = "Antes",
  afterLabel = "Depois",
}: BeforeAfterCompareProps) {
  const [originalUrl, setOriginalUrl] = useState<string | null>(null);

  useEffect(() => {
    if (!originalFile) {
      setOriginalUrl(null);
      return;
    }
    const url = URL.createObjectURL(originalFile);
    setOriginalUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [originalFile]);

  if (!originalUrl) {
    return isVideo ? (
      <video src={resultUrl} controls style={{ maxWidth: "100%", maxHeight: 400 }} />
    ) : (
      <img src={resultUrl} alt="resultado" style={{ maxWidth: "100%", maxHeight: 400 }} />
    );
  }

  return (
    <Row className="g-3">
      <Col md={6}>
        <div className="text-muted small mb-1">{beforeLabel}</div>
        {isVideo ? (
          <video src={originalUrl} controls style={{ maxWidth: "100%", maxHeight: 400 }} />
        ) : (
          <img src={originalUrl} alt="antes" style={{ maxWidth: "100%", maxHeight: 400 }} />
        )}
      </Col>
      <Col md={6}>
        <div className="text-muted small mb-1">{afterLabel}</div>
        {isVideo ? (
          <video src={resultUrl} controls style={{ maxWidth: "100%", maxHeight: 400 }} />
        ) : (
          <img src={resultUrl} alt="resultado" style={{ maxWidth: "100%", maxHeight: 400 }} />
        )}
      </Col>
    </Row>
  );
}
