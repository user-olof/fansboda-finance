#!/bin/bash

# Script to create a release branch, merge to master, and clean up
# Usage: ./scripts/create-release.sh <version>
# Example: ./scripts/create-release.sh 0.1.0

set -e  # Exit on error

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Check if version is provided
if [ -z "$1" ]; then
    echo -e "${RED}Error: Version number is required${NC}"
    echo "Usage: $0 <version>"
    echo "Example: $0 0.1.0"
    exit 1
fi

VERSION="$1"
RELEASE_BRANCH="release/$VERSION"

echo -e "${BLUE}=== Creating Release $VERSION ===${NC}"
echo ""

# Step 0: Check that you are logged into GitHub
if true; then
    echo -e "${GREEN}Step 0: Checking GitHub account status...${NC}"
    if ! gh auth status; then
        GITHUB_TOKEN=$(cat secrets/GH_TOKEN_BASIC)
        echo $GITHUB_TOKEN | gh auth login --with-token
        echo "Logged in to GitHub"
        echo ""
    fi
fi
echo ""

# Step 1: Ensure dev is pushed
if true; then
echo -e "${GREEN}Step 1: Pushing dev branch to origin...${NC}"
git push -u origin dev
echo ""
fi
# Step 2: Update remotes
if true; then
echo -e "${GREEN}Step 2: Updating remote information...${NC}"
git remote update
echo ""
fi
# Step 3: Pull latest dev
if true; then
echo -e "${GREEN}Step 3: Pulling latest changes from origin/dev...${NC}"
git pull origin dev
echo ""
fi
# Step 4: Show all branches
echo -e "${GREEN}Step 4: Current branch status...${NC}"
git branch -avv
echo ""

# Step 5: Create release branch from origin/dev
if true; then
echo -e "${GREEN}Step 5: Creating release branch $RELEASE_BRANCH from origin/dev...${NC}"
git checkout -b "$RELEASE_BRANCH" origin/dev
echo ""
fi
# Step 6: Push release branch to remote 
if true; then
echo -e "${GREEN}Step 6: Pushing release branch to origin...${NC}"
git push origin "$RELEASE_BRANCH"
echo ""
fi
# Step 7: Pause for PR review
if true; then
echo -e "${YELLOW}========================================${NC}"
echo -e "${YELLOW}⏸️  PAUSE: Manual Step Required${NC}"
echo -e "${YELLOW}========================================${NC}"
echo ""
echo "Please create a Pull Request in GitHub:"
echo "  - Compare: release/$VERSION"
echo "  - Base: master"
echo ""
echo "Review the PR and ensure everything is correct."
echo ""
read -p "Press Enter to continue after the PR is approved and merged (or Ctrl+C to cancel)..."
echo ""
fi
# Step 8: Checkout master
if true; then
echo -e "${GREEN}Step 8: Switching to master branch...${NC}"
git checkout main
echo ""
fi  
# Step 9: Show current branch
if true; then
echo -e "${GREEN}Step 9: Current branch status...${NC}"
git branch
echo ""
fi
# Step 10: Pull latest master
if true; then
echo -e "${GREEN}Step 10: Pulling latest changes from origin/master...${NC}"
git pull origin main
echo ""
fi  
# Step 11: Merge release branch into master
if true; then
echo -e "${GREEN}Step 11: Merging $RELEASE_BRANCH into master...${NC}"
git merge "$RELEASE_BRANCH" -m "Release $VERSION: Merge $RELEASE_BRANCH into master"
echo ""
fi
# Step 12: Create release tag
if true; then
    echo -e "${GREEN}Step 12: Creating release tag $VERSION...${NC}"
    
    if git tag -l | grep "$VERSION"; then
        echo -e "${YELLOW}Tag $VERSION already exists. Skipping...${NC}"
    else
        git tag -a "$VERSION" -m "Release $VERSION"
        echo "Tag $VERSION created"      
    fi
    echo ""
fi

# Step 13: Show tags
if true; then
echo -e "${GREEN}Step 13: Current tags...${NC}"
git tag
echo ""
fi
# Step 14: Push master
if true; then
echo -e "${GREEN}Step 14: Pushing master to origin...${NC}"
git push origin main
echo ""
fi
# Step 15: Push tags
if true; then
echo -e "${GREEN}Step 15: Pushing tags to origin...${NC}"
git push origin --tags
echo ""
fi

# Step 15.1: Check GitHub account status
if true; then
echo -e "${GREEN}Step 15.1: Checking GitHub account status...${NC}"
gh auth status
echo ""
fi

# Step 15.2: Create GitHub Release as draft
if true; then
echo -e "${GREEN}Step 15.5: Creating GitHub Release (draft)...${NC}"
if command -v gh &> /dev/null; then
    gh release create "$VERSION" \
        --title "Release $VERSION" \
        --notes "Release $VERSION" \
        --draft
    echo -e "${GREEN}✓ GitHub Release created as DRAFT${NC}"
    echo -e "${YELLOW}You can now edit and publish it in the GitHub UI${NC}"
else
    echo -e "${YELLOW}Warning: GitHub CLI (gh) not found.${NC}"
    echo 'Install it with: brew install gh (macOS) or see https://cli.github.com/'
    echo "Or create the release manually in GitHub UI"
fi
echo ""
fi
# Step 16: Checkout dev
if true; then
echo -e "${GREEN}Step 16: Switching to dev branch...${NC}"
git checkout dev
echo ""
fi
# Step 17: Show current branch
if true; then
echo -e "${GREEN}Step 17: Current branch status...${NC}"
git branch
echo ""
fi
# Step 18: Merge release branch into dev
if true; then
echo -e "${GREEN}Step 18: Merging $RELEASE_BRANCH into dev...${NC}"
git merge "$RELEASE_BRANCH" -m "Release $VERSION: Merge $RELEASE_BRANCH into dev"
echo ""
fi
# Step 19: Push dev
if true; then
echo -e "${GREEN}Step 19: Pushing dev to origin...${NC}"
git push origin dev
echo ""
fi
# Step 20: Delete local release branch
if true; then
echo -e "${GREEN}Step 20: Deleting local release branch...${NC}"
git branch -D "$RELEASE_BRANCH"
echo ""
fi
# Step 21: Show current branches
if true; then
echo -e "${GREEN}Step 21: Current branch status...${NC}"
git branch
echo ""
fi  
# Step 22: Delete remote release branch
if true; then
echo -e "${GREEN}Step 22: Deleting remote release branch...${NC}"
git push origin :"$RELEASE_BRANCH"
echo ""
fi
# Step 23: Final branch status
if true; then
echo -e "${GREEN}Step 23: Final branch status...${NC}"
git branch -avv
echo ""
fi

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}✅ Release $VERSION completed successfully!${NC}"
echo -e "${GREEN}========================================${NC}"