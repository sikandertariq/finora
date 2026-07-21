"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { login } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

const schema = z.object({
  username: z.string().min(1, "Enter your username."),
  password: z.string().min(1, "Enter your password."),
});
type FormValues = z.infer<typeof schema>;

export function LoginForm() {
  const { signIn } = useAuth();
  const [error, setError] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    setValue,
    formState: { errors, isSubmitting },
  } = useForm<FormValues>({ resolver: zodResolver(schema) });

  async function onSubmit(values: FormValues) {
    setError(null);
    try {
      const session = await login(values.username, values.password);
      signIn(session);
    } catch {
      setError("Couldn't sign in — check your username and password.");
    }
  }

  function tryDemo() {
    setValue("username", process.env.NEXT_PUBLIC_DEMO_USERNAME ?? "demo");
    setValue("password", process.env.NEXT_PUBLIC_DEMO_PASSWORD ?? "demo-password");
    void handleSubmit(onSubmit)();
  }

  return (
    <form
      onSubmit={handleSubmit(onSubmit)}
      className="flex w-full max-w-sm flex-col gap-4"
    >
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="username">Username</Label>
        <Input id="username" autoComplete="username" {...register("username")} />
        {errors.username && (
          <p className="text-sm text-destructive">{errors.username.message}</p>
        )}
      </div>
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="password">Password</Label>
        <Input
          id="password"
          type="password"
          autoComplete="current-password"
          {...register("password")}
        />
        {errors.password && (
          <p className="text-sm text-destructive">{errors.password.message}</p>
        )}
      </div>
      {error && <p className="text-sm text-destructive">{error}</p>}
      <Button type="submit" disabled={isSubmitting}>
        {isSubmitting ? "Signing in…" : "Sign in"}
      </Button>
      <div className="rounded-md border border-amber-300 bg-amber-50 p-3 text-sm text-amber-950">
        <p className="font-medium">Public portfolio demo</p>
        <p className="mt-1">This data resets regularly. Do not upload real or sensitive receipts.</p>
        <Button
          className="mt-3"
          type="button"
          variant="outline"
          onClick={tryDemo}
          disabled={isSubmitting}
        >
          Try the demo
        </Button>
      </div>
    </form>
  );
}
