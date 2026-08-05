import { Routes, Route } from "react-router-dom";
import AppNav from "./components/AppNav";
import Landing from "./routes/Landing";
import Workbench from "./routes/Workbench";
import PolicyLibrary from "./routes/PolicyLibrary";
import Report from "./routes/Report";

export default function App() {
  return (
    <>
      <AppNav />
      <Routes>
        <Route path="/" element={<Landing />} />
        <Route path="/workbench" element={<Workbench />} />
        <Route path="/policies" element={<PolicyLibrary />} />
        <Route path="/report" element={<Report />} />
      </Routes>
    </>
  );
}
