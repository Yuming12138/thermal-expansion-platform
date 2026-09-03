import { Navigate, Route, Routes } from "react-router-dom";
import AppShell from "./components/AppShell";
import AboutPage from "./pages/AboutPage";
import DatabasePage from "./pages/DatabasePage";
import LandscapePage from "./pages/LandscapePage";
import PredictPage from "./pages/PredictPage";
import ZtePage from "./pages/ZtePage";

export default function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<Navigate to="/database" replace />} />
        <Route path="/database" element={<DatabasePage />} />
        <Route path="/predict" element={<PredictPage />} />
        <Route path="/landscape" element={<LandscapePage />} />
        <Route path="/zte" element={<ZtePage />} />
        <Route path="/about" element={<AboutPage />} />
        <Route path="*" element={<Navigate to="/database" replace />} />
      </Route>
    </Routes>
  );
}
