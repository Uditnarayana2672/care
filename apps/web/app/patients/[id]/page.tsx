import PatientView from "@/components/PatientView";

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <PatientView id={id} />;
}
