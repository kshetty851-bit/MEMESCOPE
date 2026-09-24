"use client";

import { useParams } from "next/navigation";

import { FamilyMemberPage } from "@/components/real-wallet/family";

export default function Page() {
  const { member } = useParams<{ member: string }>();
  return <FamilyMemberPage member={member ?? ""} />;
}
