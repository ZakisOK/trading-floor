import { redirect } from "next/navigation";

export default function CopyTradeRedirect() {
  redirect("/floor?tab=symbols");
}
