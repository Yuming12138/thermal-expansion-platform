import { useCallback, useEffect, useState } from "react";
import { loadMaterialContext, saveMaterialContext, type MaterialContext } from "./materialContext";

/**
 * 材料上下文的 React 绑定：localStorage 持久 + storage 事件跨标签同步。
 * 任意工作区调用 setContext 后，外壳的材料条即时更新。
 */
export function useMaterialContext(): {
  context: MaterialContext | null;
  setContext: (context: MaterialContext | null) => void;
} {
  const [context, setContextState] = useState<MaterialContext | null>(() => loadMaterialContext());

  useEffect(() => {
    const onStorage = (event: StorageEvent) => {
      if (event.key === "tep.material-context.v1" || event.key === null) {
        setContextState(loadMaterialContext());
      }
    };
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, []);

  const setContext = useCallback((next: MaterialContext | null) => {
    saveMaterialContext(next);
    setContextState(next);
  }, []);

  return { context, setContext };
}
