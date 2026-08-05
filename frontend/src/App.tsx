import { Routes, Route } from "react-router-dom";
import Landing from "./routes/Landing";
import Workbench from "./routes/Workbench";

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Landing />} />
      <Route path="/workbench" element={<Workbench />} />
    </Routes>
  );
}
