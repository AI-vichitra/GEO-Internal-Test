"use client";

import { SignupPage } from "@/components/signup-page";
import { useRouter } from "next/navigation";

export default function Login() {
    const router = useRouter();

    const handleSuccess = () => {
        router.push("/dashboard");
    };

    return (
        <SignupPage onSuccess={handleSuccess} />
    );
}
