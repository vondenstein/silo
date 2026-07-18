import { TextField } from "@/components/form/text-field"

export function DateField(props: { label: string; description?: string }) {
  return <TextField type="date" {...props} />
}
