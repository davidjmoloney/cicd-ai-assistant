#!/usr/bin/env python3
"""
Simple test script for the pr_generator.
"""
import json
import sys
from pathlib import Path

from agents.agent_handler import AgentHandler, FixPlan
from github.pr_generator import PRGenerator


CONTEXT_FILE = Path(__file__).parent / "context_output.json"
AGENT_FILE_EDITS = Path(__file__).parent / "agent_output.json"
MAKE_LLM_CALL = False

def main():
    
    generated_fix_plan = None
    
    if MAKE_LLM_CALL:
        # Check API key is set
        from agents.llm_provider import OPENAI_API_KEY
        if not OPENAI_API_KEY:
            print("ERROR: OPENAI_API_KEY environment variable not set")
            sys.exit(1)
        print("API key configured")

        # Load context
        print(f"Loading context from {CONTEXT_FILE}")
        with open(CONTEXT_FILE) as f:
            context = json.load(f)
        print(f"Loaded {context['group']['group_size']} signals")

        # Call agent
        print("\nCalling OpenAI...")
        handler = AgentHandler(provider="openai")
        result = handler.generate_fix_plan(context)

        # Fail if 
        if not result.success:
            print(f"\nFAILED: {result.error}")
            if result.llm_error:
                print(f"Raw response: {result.llm_error}")
                return 
            
        # Otherwise continue
        print("\nSuccess!\n--- Full Fix Plan JSON ---")
        generated_fix_plan = result.fix_plan
        print(json.dumps(generated_fix_plan.to_dict(), indent=2))
    else:
        with open(AGENT_FILE_EDITS) as f:
            generated_fix_plan = FixPlan.from_dict(json.load(f))

    # Create PR
    pr_generator = PRGenerator()
    pr_result = pr_generator.create_pr(fix_plan=generated_fix_plan, base_branch="main")

    if pr_result.success:
        print("\nPR GENERATION SUCCESS!")
        print(f"PR url: {pr_result.pr_url}")
        print(f"Branch Name: {pr_result.branch_name}")
        print(f"Files Changed: {len(pr_result.files_changed)}")
    else:
        print(f"PR Generation FAILED: {pr_result.error}")

if __name__ == "__main__":
    main()
 