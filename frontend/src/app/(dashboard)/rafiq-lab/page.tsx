/**
 * The route. Everything else lives in `src/labs/rafiq/`.
 *
 * Next's App Router resolves pages from the filesystem, so a route has to be a
 * file in `app/`. This is that file and nothing more — a re-export, so the lab
 * stays one directory and this page cannot accumulate logic of its own.
 */
export { RafiqLabPage as default } from "@/labs/rafiq/page";
