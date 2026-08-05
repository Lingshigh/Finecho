import { Routes, Route } from "react-router-dom";
import Landing from "./routes/Landing";
import Workbench from "./routes/Workbench";
import PolicyLibrary from "./routes/PolicyLibrary";

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Landing />} />
      <Route path="/workbench" element={<Workbench />} />
      <Route path="/policies" element={<PolicyLibrary />} />
    </Routes>
  );
}
