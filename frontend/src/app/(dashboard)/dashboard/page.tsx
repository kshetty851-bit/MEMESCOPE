import { redirect } from "next/navigation";

/**
 * There is no Dashboard in MEMESCOPE — there is a Command Center. The old
 * route is kept only so existing links and bookmarks land in the right place.
 */
export default function DashboardRedirect() {
  redirect("/command");
}
