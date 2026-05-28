import { Lightbulb } from "lucide-react";

export default function AutomationApp() {
  return (
    <div className="flex flex-col items-center justify-center h-full text-slate-500">
      <Lightbulb size={36} className="text-slate-600 mb-3" />
      <p className="text-sm font-medium text-slate-400">Automation</p>
      <p className="text-xs mt-1">Home Assistant voice and MCP tooling enabled; UI controls coming soon</p>
    </div>
  );
}
